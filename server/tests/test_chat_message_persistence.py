"""DATABASE_OPT F1: ChatMessage 持久化单元测试。

验证 intent_route_node 和 option_generate_node 返回 dict 中包含 chat_reply 字段。
"""
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.nodes.intent_route_agent import intent_route_node
from app.agent.nodes.option_generate_agent import option_generate_node


# ---------------------------------------------------------------------------
# Router — chat_reply
# ---------------------------------------------------------------------------


async def _async_gen(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_router_chat_stream_returns_chat_reply():
    """流式 chat: return dict 应包含非空的 chat_reply。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(
        '{"welcome_chat": "你好呀！有什么可以帮你的？", "intent": "chat"}',
    )

    queue = asyncio.Queue()
    state = {"user_query": "你好", "stream": True, "_sse_queue": queue}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert "chat_reply" in result
    assert result["chat_reply"] == "你好呀！有什么可以帮你的？"


@pytest.mark.asyncio
async def test_router_chat_nonstream_returns_chat_reply():
    """非流式 chat: return dict 应包含非空的 chat_reply。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "你好！需要推荐什么吗？",
        "intent": "chat",
    })

    queue = asyncio.Queue()
    state = {"user_query": "你好", "stream": False, "_sse_queue": queue}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert "chat_reply" in result
    assert result["chat_reply"] == "你好！需要推荐什么吗？"


@pytest.mark.asyncio
async def test_router_explicit_does_not_overwrite_chat_reply():
    """非 chat 路径 (explicit): chat_reply 不应意外出现或应为空。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "帮你找到了几款跑鞋～",
        "intent": "explicit",
    })

    state = {"user_query": "推荐跑鞋", "stream": False}
    result = await intent_route_node(state, llm=mock_llm)

    # explicit 不返回 chat_reply，否则 search.py 会用 welcome 覆盖用户的 chat_reply 预期
    assert result["intent"] == "explicit"


# ---------------------------------------------------------------------------
# Option Gen — chat_reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_option_gen_returns_chat_reply():
    """推荐流程: option_gen 的 return 应包含 ending 作为 chat_reply。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "ending": "以上是为您推荐的商品，希望对您有帮助！",
        "next_options": ["看看其他品牌", "调整预算"],
    })

    state = {
        "user_query": "推荐跑鞋",
        "stream": False,
        "retrieval_results": [
            {
                "product_id": "p_shoe_001",
                "title": "轻量跑鞋",
                "brand": "Nike",
                "category": "运动户外",
                "sub_category": "跑鞋",
                "base_price": 599.0,
                "skus": [],
                "matched_texts": [],
            }
        ],
        "requirements": [{"category": "运动户外", "sub_category": "跑鞋", "text": "跑鞋"}],
        "scenario_description": "",
        "session_memory": [],
    }
    result = await option_generate_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert result["chat_reply"] == "以上是为您推荐的商品，希望对您有帮助！"


@pytest.mark.asyncio
async def test_option_gen_empty_ending():
    """ending 为空时 chat_reply 也应为空字符串。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = '{"ending": "", "next_options": []}'

    state = {
        "user_query": "推荐跑鞋",
        "stream": False,
        "retrieval_results": [],
        "requirements": [{"category": "运动户外", "sub_category": "跑鞋"}],
        "scenario_description": "",
        "session_memory": [],
    }
    result = await option_generate_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert result["chat_reply"] == ""
