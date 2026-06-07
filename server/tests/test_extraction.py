"""Extraction 节点测试 — 重构后三步流程。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.nodes.extraction import (
    extraction_node,
    _build_context_with_memory,
    _parse_json_array,
)


# ---------------------------------------------------------------------------
# _parse_json_array 测试
# ---------------------------------------------------------------------------

def test_parse_json_array_empty():
    assert _parse_json_array("") == []
    assert _parse_json_array(None) == []


def test_parse_json_array_basic():
    result = _parse_json_array('[{"a": 1}]')
    assert len(result) == 1
    assert result[0]["a"] == 1


def test_parse_json_array_with_markdown_fence():
    result = _parse_json_array('```json\n[{"a": 1}]\n```')
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _build_context_with_memory 测试
# ---------------------------------------------------------------------------

def test_build_context_empty_memory():
    """无历史 memory 时，context 只包含当前查询。"""
    context = _build_context_with_memory(
        "要轻量的跑鞋",
        [{"category": "服饰运动", "sub_category": "跑步鞋", "brand": None}],
        [],
    )
    assert "跑步鞋" in context
    assert "要轻量的跑鞋" in context
    assert "(无)" in context


def test_build_context_with_history():
    """有历史 memory 时，应拼接历史查询和当前查询。"""
    memory = [{
        "category": "服饰运动",
        "sub_category": "跑步鞋",
        "queries": [
            {"query": "帮我推荐跑鞋", "timestamp": "2026-06-04T10:00:00"},
            {"query": "要轻量的", "timestamp": "2026-06-04T10:01:00"},
        ],
    }]
    context = _build_context_with_memory(
        "预算500以内",
        [{"category": "服饰运动", "sub_category": "跑步鞋", "brand": None}],
        memory,
    )
    assert "帮我推荐跑鞋" in context
    assert "要轻量的" in context
    assert "预算500以内" in context


def test_build_context_multiple_categories():
    """多品类时每品类有独立的历史+当前拼接段。"""
    memory = [
        {"category": "美妆护肤", "sub_category": "防晒",
         "queries": [{"query": "夏天到了", "timestamp": "2026-06-01"}]},
    ]
    context = _build_context_with_memory(
        "推荐不粘腻的防晒和舒服的跑鞋",
        [
            {"category": "美妆护肤", "sub_category": "防晒", "brand": None},
            {"category": "服饰运动", "sub_category": "跑步鞋", "brand": None},
        ],
        memory,
    )
    assert "防晒" in context
    assert "跑步鞋" in context
    assert "夏天到了" in context


# ---------------------------------------------------------------------------
# extraction_node 测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extraction_new_format_output():
    """Extraction 应输出新格式 requirements 列表。"""
    mock_llm = AsyncMock()

    # Step1 响应: 品类提取
    step1_json = json.dumps([{"category": "数码电子", "sub_category": "蓝牙耳机", "brand": None}])
    # Step3 响应: 意图提取
    step3_json = json.dumps([{
        "category": "数码电子",
        "sub_category": "蓝牙耳机",
        "text": "音质好 续航久",
        "min_price": 0,
        "max_price": 200,
        "order_num": 1,
        "brand": None,
    }])

    responses = [step1_json, step3_json]

    async def mock_chat(*args, **kwargs):
        return responses.pop(0)

    mock_llm.chat = mock_chat

    # Mock db_session_factory
    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    # Mock fetch_category_context 返回空
    mock_session.execute.return_value.fetchall.return_value = []

    state = {
        "user_query": "200元以下的蓝牙耳机",
        "session_memory": [],
        
    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await extraction_node(
            state, llm=mock_llm,
            db_session_factory=mock_session_factory,
        )

    assert "requirements" in result
    reqs = result["requirements"]
    assert isinstance(reqs, list)
    assert len(reqs) >= 1
    assert "category" in reqs[0]
    assert "text" in reqs[0]


@pytest.mark.asyncio
async def test_extraction_fallback_on_llm_error():
    """Step1 LLM 失败时，fallback 为空品类 + 原查询语义检索。"""
    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM error")

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)

    state = {
        "user_query": "蓝牙耳机",
        "session_memory": [],
        
    }

    result = await extraction_node(
        state, llm=mock_llm,
        db_session_factory=mock_session_factory,
    )

    assert "requirements" in result
    reqs = result["requirements"]
    assert isinstance(reqs, list)
    assert len(reqs) >= 1


@pytest.mark.asyncio
async def test_extraction_uses_user_query():
    """Extraction 应使用 user_query 进行品类提取。"""
    mock_llm = AsyncMock()

    step1_json_b = json.dumps([{"category": "服饰运动", "sub_category": "跑步鞋", "brand": None}])
    step3_json_b = json.dumps([{
        "category": "服饰运动", "sub_category": "跑步鞋",
        "text": "轻量化 舒适", "min_price": 0, "max_price": 500,
        "order_num": 1, "brand": None,
    }])

    responses_b = [step1_json_b, step3_json_b]

    async def mock_chat_b(*args, **kwargs):
        return responses_b.pop(0)

    mock_llm.chat = mock_chat_b

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    state = {
        "user_query": "要轻量的跑鞋",
        "session_memory": [],

    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await extraction_node(
            state, llm=mock_llm,
            db_session_factory=mock_session_factory,
        )

    assert "requirements" in result
    reqs = result["requirements"]
    assert len(reqs) >= 1
