"""Scenario Gen 节点测试 — 重构后新格式。"""
import json
import pytest
from unittest.mock import patch
from app.agent.nodes.scenario_gen import scenario_gen_node, _cross_validate_categories


# ---------------------------------------------------------------------------
# Helper: make a sync llm mock with async chat
# ---------------------------------------------------------------------------

def _make_mock_llm(returns=None, error=None):
    """创建带 async chat 方法的 mock LLM。"""
    from unittest.mock import MagicMock
    mock = MagicMock()

    async def mock_chat(*args, **kwargs):
        if error:
            raise error
        return returns

    mock.chat = mock_chat
    return mock


# ---------------------------------------------------------------------------
# Scenario Gen 节点测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_gen_basic():
    """Scenario Gen 应返回 scenario_description + 新格式 requirements。"""
    mock_llm = _make_mock_llm(returns=json.dumps({
        "scenario_description": "去三亚度假准备方案",
        "requirements": [
            {"category": "面部护肤", "sub_category": "防晒霜",
             "text": "高倍数防晒", "min_price": 0, "max_price": 4294967295,
             "order_num": 1, "brand": None},
            {"category": "服饰", "sub_category": "墨镜",
             "text": "偏光 防紫外线", "min_price": 0, "max_price": 4294967295,
             "order_num": 1, "brand": None},
        ]
    }))

    state = {
        "user_query": "去三亚度假需要准备什么",
        "rewritten_query": "去三亚度假需要准备什么",
        "conversation_history": [],
        "session_memory": [],
    }
    result = await scenario_gen_node(state, llm=mock_llm, category_list="面部护肤|防晒霜\n服饰|墨镜")

    assert "scenario_description" in result
    assert "requirements" in result
    reqs = result["requirements"]
    assert isinstance(reqs, list)
    assert len(reqs) == 2
    assert reqs[0]["category"] == "面部护肤"


@pytest.mark.asyncio
async def test_scenario_gen_fallback_on_llm_error():
    """LLM 失败时应 fallback，返回空 requirements。"""
    mock_llm = _make_mock_llm(error=Exception("LLM error"))

    state = {
        "user_query": "去三亚度假",
        "rewritten_query": "去三亚度假",
        "conversation_history": [],
        "session_memory": [],
    }
    result = await scenario_gen_node(state, llm=mock_llm, category_list="面部护肤|防晒霜")

    assert "requirements" in result
    assert result["requirements"] == []


# ---------------------------------------------------------------------------
# Cross-validation 测试
# ---------------------------------------------------------------------------


def test_cross_validate_exact_match():
    lookup = {("面部护肤", "防晒霜"), ("服饰", "墨镜")}
    result = _cross_validate_categories("面部护肤", "防晒霜", lookup)
    assert result == ("面部护肤", "防晒霜")


def test_cross_validate_case_insensitive_match():
    lookup = {("面部护肤", "防晒霜"), ("服饰", "墨镜")}
    result = _cross_validate_categories("面部护肤", "防晒霜 ", lookup)
    assert result == ("面部护肤", "防晒霜")

    result2 = _cross_validate_categories(" 面部护肤", "防晒霜", lookup)
    assert result2 == ("面部护肤", "防晒霜")


def test_cross_validate_no_match_returns_none():
    lookup = {("面部护肤", "防晒霜")}
    result = _cross_validate_categories("不存在的品类", "虚构子类", lookup)
    assert result == (None, None)


def test_cross_validate_none_input():
    lookup = {("面部护肤", "防晒霜")}
    result = _cross_validate_categories(None, None, lookup)
    assert result == (None, None)


def test_cross_validate_partial_match_category_only():
    lookup = {("面部护肤", "防晒霜")}
    result = _cross_validate_categories("面部护肤", "不存在子类", lookup)
    assert result == (None, None)


@pytest.mark.asyncio
async def test_scenario_gen_cross_validates_llm_output():
    """Scenario Gen 应对 LLM 输出的品类做交叉校验。"""
    mock_llm = _make_mock_llm(returns=json.dumps({
        "scenario_description": "去三亚度假准备方案",
        "requirements": [
            {"category": "面部护肤", "sub_category": " 防晒霜 ",
             "text": "高倍数防晒", "min_price": 0, "max_price": 4294967295,
             "order_num": 1, "brand": None},
        ]
    }))

    state = {
        "user_query": "去三亚度假需要准备什么",
        "rewritten_query": "去三亚度假需要准备什么",
        "conversation_history": [],
        "session_memory": [],
    }

    result = await scenario_gen_node(
        state, llm=mock_llm,
        category_list="面部护肤|防晒霜\n服饰|墨镜\n面部护肤|洗面奶"
    )

    reqs = result["requirements"]
    assert len(reqs) == 1
    assert reqs[0]["category"] == "面部护肤"
    assert reqs[0]["sub_category"] == "防晒霜"  # 空格被修正
