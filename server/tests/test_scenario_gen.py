"""MCL-A6: Scenario Gen 节点测试。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.nodes.scenario_gen import scenario_gen_node, _cross_validate_categories


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


# ---------------------------------------------------------------------------
# ScenarioGen completion: cross-validation of category/sub_category
# ---------------------------------------------------------------------------


def test_cross_validate_exact_match():
    """精确匹配时保持 category/sub_category 不变。"""
    lookup = {("面部护肤", "防晒霜"), ("服饰", "墨镜")}
    result = _cross_validate_categories("面部护肤", "防晒霜", lookup)
    assert result == ("面部护肤", "防晒霜")


def test_cross_validate_case_insensitive_match():
    """大小写差异应模糊匹配到正确值。"""
    lookup = {("面部护肤", "防晒霜"), ("服饰", "墨镜")}
    result = _cross_validate_categories("面部护肤", "防晒霜 ", lookup)
    assert result == ("面部护肤", "防晒霜")

    # 测试前导/尾随空格
    result2 = _cross_validate_categories(" 面部护肤", "防晒霜", lookup)
    assert result2 == ("面部护肤", "防晒霜")


def test_cross_validate_no_match_returns_none():
    """无法匹配时返回 (None, None) 回退到 default 组。"""
    lookup = {("面部护肤", "防晒霜")}
    result = _cross_validate_categories("不存在的品类", "虚构子类", lookup)
    assert result == (None, None)


def test_cross_validate_none_input():
    """输入为 None 时返回 (None, None)。"""
    lookup = {("面部护肤", "防晒霜")}
    result = _cross_validate_categories(None, None, lookup)
    assert result == (None, None)


def test_cross_validate_partial_match_category_only():
    """category 匹配但 sub_category 不匹配时返回 (None, None)。"""
    lookup = {("面部护肤", "防晒霜")}
    result = _cross_validate_categories("面部护肤", "不存在子类", lookup)
    assert result == (None, None)


@pytest.mark.asyncio
async def test_scenario_gen_cross_validates_llm_output():
    """Scenario Gen 应对 LLM 输出的品类做交叉校验。"""
    mock_llm = AsyncMock()
    # LLM 返回的品类有空格差异
    mock_llm.chat.return_value = json.dumps({
        "scenario_description": "去三亚度假准备方案",
        "requirements": {
            "sub_queries": [
                {"text": "防晒霜", "strategy": "keyword",
                 "category": "面部护肤", "sub_category": " 防晒霜 ",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
            ]
        }
    })

    state = {
        "user_query": "去三亚度假需要准备什么",
        "conversation_history": [],
    }

    # category_list 中的品类不含空格
    result = await scenario_gen_node(
        state, llm=mock_llm,
        category_list="面部护肤|防晒霜\n服饰|墨镜\n面部护肤|洗面奶"
    )

    # 交叉校验后 sub_category 应被修正为无空格的版本
    subs = result["requirements"]["sub_queries"]
    assert len(subs) == 1
    assert subs[0]["category"] == "面部护肤"
    assert subs[0]["sub_category"] == "防晒霜"  # 空格被修正
