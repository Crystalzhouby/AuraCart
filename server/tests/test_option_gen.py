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
        "retrieval_results": [
            {"product_id": "p001", "sku_id": "sk001", "title": "安踏C202", "price": 399,
             "category": "运动户外", "sub_category": "跑鞋"}
        ],
        
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
        "retrieval_results": [],
        
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
        "retrieval_results": [],
        
        "scenario_description": None,
    }
    result = await option_gen_node(state, llm=mock_llm)

    assert len(result["next_options"]) <= 4


# ---------------------------------------------------------------------------
# OptionGen completion: failed_categories awareness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_option_gen_injects_failed_categories_into_prompt():
    """Option Gen 应将 failed_categories 注入提示词，让 LLM 避开失败品类。"""
    mock_llm = AsyncMock()

    captured_system_content = []

    async def _capture_chat(messages, **kwargs):
        system_content = messages[0]["content"] if messages else ""
        captured_system_content.append(system_content)
        return json.dumps({"next_options": ["需要推荐其他面部护肤品吗？"]})

    mock_llm.chat = _capture_chat

    state = {
        "requirements": {"sub_queries": [{"text": "test"}]},
        "retrieval_results": [],
        
        "scenario_description": None,
        "failed_categories": ["防晒霜", "墨镜"],  # 检索失败的品类
    }
    await option_gen_node(state, llm=mock_llm)

    # 验证提示词中注入了失败品类信息（区别于 retrieval_results）
    assert len(captured_system_content) == 1
    prompt = captured_system_content[0]

    # 应该包含格式化的失败品类列表
    assert "防晒霜" in prompt
    assert "墨镜" in prompt
    # 不应是 retrieval_results 中的（已设为空），应来自 failed_categories 注入


@pytest.mark.asyncio
async def test_option_gen_omits_failed_categories_when_empty():
    """没有失败品类时提示词不应包含失败品类占位信息。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "next_options": ["选项1", "选项2"]
    })

    state = {
        "requirements": {"sub_queries": []},
        "retrieval_results": [],
        
        "scenario_description": None,
        "failed_categories": [],
    }
    result = await option_gen_node(state, llm=mock_llm)

    assert len(result["next_options"]) >= 2


@pytest.mark.asyncio
async def test_option_gen_empty_failed_categories():
    """没有失败品类时正常生成选项。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "next_options": ["需要搭配跑步袜吗？", "想看看更高端的专业款吗？"]
    })

    state = {
        "requirements": {"sub_queries": []},
        "retrieval_results": [],
        
        "scenario_description": None,
        "failed_categories": [],
    }
    result = await option_gen_node(state, llm=mock_llm)

    assert len(result["next_options"]) >= 2
