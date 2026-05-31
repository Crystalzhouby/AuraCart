"""MCL-A6: Scenario Gen 节点测试。"""
import json
import pytest
from unittest.mock import AsyncMock
from app.agent.nodes.scenario_gen import scenario_gen_node


@pytest.mark.asyncio
async def test_scenario_gen_basic():
    """Scenario Gen 应返回 scenario_description + requirements with category fields。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "scenario_description": "去三亚度假准备方案",
        "requirements": {
            "sub_queries": [
                {"text": "防晒霜", "strategy": "keyword", "category": "面部护肤", "sub_category": "防晒霜",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
                {"text": "墨镜", "strategy": "keyword", "category": "服饰", "sub_category": "墨镜",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
            ]
        }
    })

    state = {
        "user_query": "去三亚度假需要准备什么",
        "conversation_history": [],
    }
    result = await scenario_gen_node(state, llm=mock_llm, category_list="面部护肤|防晒霜\n服饰|墨镜")

    assert "scenario_description" in result
    assert "requirements" in result
    assert len(result["requirements"]["sub_queries"]) == 2
    assert result["requirements"]["sub_queries"][0]["category"] == "面部护肤"


@pytest.mark.asyncio
async def test_scenario_gen_fallback_on_llm_error():
    """LLM 失败时应 fallback，返回空 SubQuery（由上层处理回退到 extraction）。"""
    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM error")

    state = {
        "user_query": "去三亚度假",
        "conversation_history": [],
    }
    result = await scenario_gen_node(state, llm=mock_llm, category_list="面部护肤|防晒霜")

    # Fallback 返回空 requirements，graph 层将回退到 extraction
    assert "requirements" in result
    assert result["requirements"]["sub_queries"] == []
