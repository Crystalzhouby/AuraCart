"""MCL-A5: Extraction 节点测试。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.nodes.extraction import extraction_node


async def _async_gen(*items):
    """将多个字符串转为异步生成器。"""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_extraction_basic():
    """Extraction 应解析 LLM 返回的 SubQuery JSON 并返回 requirements。"""
    mock_llm = MagicMock()
    response_json = json.dumps([
        {"text": "蓝牙耳机", "strategy": "keyword",
         "field": None, "operator": None, "value": None, "expanded_values": None,
         "category": "数码电子", "sub_category": "蓝牙耳机"},
        {"text": "", "strategy": "structured_filter",
         "field": "price", "operator": "lt", "value": 200, "expanded_values": None,
         "category": None, "sub_category": None},
    ])
    mock_llm.chat_stream.return_value = _async_gen(response_json)

    state = {
        "user_query": "200元以下的蓝牙耳机",
        "conversation_history": [],
    }
    result = await extraction_node(state, llm=mock_llm)

    assert "requirements" in result
    assert len(result["requirements"]["sub_queries"]) == 2
    assert result["requirements"]["sub_queries"][0]["category"] == "数码电子"


@pytest.mark.asyncio
async def test_extraction_includes_conversation_history_append():
    """Extraction 应追加 conversation_history。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(json.dumps([
        {"text": "跑鞋", "strategy": "keyword",
         "field": None, "operator": None, "value": None, "expanded_values": None,
         "category": "运动户外", "sub_category": "跑鞋"},
    ]))

    state = {
        "user_query": "跑鞋推荐",
        "conversation_history": [],
    }
    result = await extraction_node(state, llm=mock_llm)

    assert "conversation_history" in result
    assert len(result["conversation_history"]) == 1


@pytest.mark.asyncio
async def test_extraction_fallback_on_llm_error():
    """LLM 失败时 fallback 为语义检索。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.side_effect = Exception("LLM error")

    state = {
        "user_query": "蓝牙耳机",
        "conversation_history": [],
    }
    result = await extraction_node(state, llm=mock_llm)

    assert "requirements" in result
    subs = result["requirements"]["sub_queries"]
    assert len(subs) == 1
    assert subs[0]["strategy"] == "semantic"
    assert subs[0]["text"] == "蓝牙耳机"
