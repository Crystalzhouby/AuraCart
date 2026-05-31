"""MCL-A7: Option Gen 节点测试。"""
import json
import pytest
from unittest.mock import AsyncMock
from app.agent.nodes.option_gen import option_gen_node


@pytest.mark.asyncio
async def test_option_gen_basic():
    """Option Gen 应返回 2-4 条下一步选项。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "next_options": [
            "需要搭配跑步袜吗？",
            "想看看更高端的专业款吗？",
        ]
    })

    state = {
        "requirements": {"sub_queries": [{"text": "跑鞋", "strategy": "keyword"}]},
        "products_summary": [
            {"product_id": "p001", "sku_id": "sk001", "title": "安踏C202", "price": 399,
             "category": "运动户外", "sub_category": "跑鞋"}
        ],
        "conversation_history": [],
        "scenario_description": None,
    }
    result = await option_gen_node(state, llm=mock_llm)

    assert "next_options" in result
    assert 2 <= len(result["next_options"]) <= 4


@pytest.mark.asyncio
async def test_option_gen_fallback_on_error():
    """LLM 失败时 Option Gen 应返回空列表。"""
    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM error")

    state = {
        "requirements": {"sub_queries": [{"text": "test"}]},
        "products_summary": [],
        "conversation_history": [],
        "scenario_description": None,
    }
    result = await option_gen_node(state, llm=mock_llm)

    assert "next_options" in result
    assert result["next_options"] == []


@pytest.mark.asyncio
async def test_option_gen_truncates_too_many():
    """LLM 返回超过 4 条选项时应截断。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "next_options": ["选项1", "选项2", "选项3", "选项4", "选项5", "选项6"]
    })

    state = {
        "requirements": {"sub_queries": []},
        "products_summary": [],
        "conversation_history": [],
        "scenario_description": None,
    }
    result = await option_gen_node(state, llm=mock_llm)

    assert len(result["next_options"]) <= 4
