"""Extraction 节点测试 — 重构后三步流程。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.nodes.intent_extract_agent import (
    intent_extract_node,
    _build_context_with_memory,
    _extract_categories_and_brands,
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

@pytest.mark.asyncio
async def test_build_context_empty_memory():
    """无历史记录时，context 只包含当前查询。"""
    with patch("app.agent.nodes.intent_extract_agent.get_chat_history_window",
               AsyncMock(return_value="(无历史记录)")):
        context = await _build_context_with_memory(
            "要轻量的跑鞋",
            [{"category": "服饰运动", "sub_category": "跑步鞋", "brand": None}],
            MagicMock(),
            "test-cid",
        )
    assert "跑步鞋" in context
    assert "要轻量的跑鞋" in context


@pytest.mark.asyncio
async def test_build_context_with_history():
    """有历史记录时，应拼接历史查询和当前查询。"""
    history_text = "用户: 帮我推荐跑鞋\n助手: 好的\n用户: 要轻量的\n助手: 有轻量化的"
    with patch("app.agent.nodes.intent_extract_agent.get_chat_history_window",
               AsyncMock(return_value=history_text)):
        context = await _build_context_with_memory(
            "预算500以内",
            [{"category": "服饰运动", "sub_category": "跑步鞋", "brand": None}],
            MagicMock(),
            "test-cid",
        )
    assert "帮我推荐跑鞋" in context
    assert "要轻量的" in context
    assert "预算500以内" in context


@pytest.mark.asyncio
async def test_build_context_multiple_categories():
    """多品类时每品类有独立的历史+当前拼接段。"""
    history_text = "用户: 夏天到了"
    with patch("app.agent.nodes.intent_extract_agent.get_chat_history_window",
               AsyncMock(return_value=history_text)):
        context = await _build_context_with_memory(
            "推荐不粘腻的防晒和舒服的跑鞋",
            [
                {"category": "美妆护肤", "sub_category": "防晒", "brand": None},
                {"category": "服饰运动", "sub_category": "跑步鞋", "brand": None},
            ],
            MagicMock(),
            "test-cid",
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
        "conversation_id": "",
        
    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await intent_extract_node(
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
        "conversation_id": "",
        
    }

    result = await intent_extract_node(
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
        "conversation_id": "",

    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await intent_extract_node(
            state, llm=mock_llm,
            db_session_factory=mock_session_factory,
        )

    assert "requirements" in result
    reqs = result["requirements"]
    assert len(reqs) >= 1


# ---------------------------------------------------------------------------
# EXTRACT_OPT: Step 1 注入对话历史测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step1_prompt_contains_recent_queries_placeholder():
    """验证 INTENT_EXTRACT_STEP1_SYSTEM 模板已包含 {recent_queries} 占位符和时间提示。"""
    from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP1_SYSTEM
    assert "{recent_queries}" in INTENT_EXTRACT_STEP1_SYSTEM
    assert "越近的查询越重要" in INTENT_EXTRACT_STEP1_SYSTEM


@pytest.mark.asyncio
async def test_step1_with_history_infers_category():
    """会话有历史记录时，prompt 应包含格式化后的历史查询文本。"""
    mock_llm = AsyncMock()

    captured_messages = []
    async def capture_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return json.dumps([{"category": "服饰运动", "sub_category": "跑步鞋", "brand": None}])

    mock_llm.chat = capture_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    history_text = "用户: 要轻量的\n助手: 好的\n用户: 帮我推荐跑鞋\n助手: 推荐了几款"

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))), \
         patch("app.agent.nodes.intent_extract_agent.get_chat_history_window",
               AsyncMock(return_value=history_text)):
        await _extract_categories_and_brands(
            "预算500以内", mock_llm, mock_session_factory, "test-cid",
        )

    system_prompt = captured_messages[0]["content"]
    assert "要轻量的" in system_prompt
    assert "帮我推荐跑鞋" in system_prompt


@pytest.mark.asyncio
async def test_step1_empty_memory_shows_placeholder():
    """conversation_id="" 时 prompt 包含 '(无历史记录)'。"""
    mock_llm = AsyncMock()

    captured_messages = []
    async def capture_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return json.dumps([{"category": "美妆护肤", "sub_category": "防晒", "brand": None}])

    mock_llm.chat = capture_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        await _extract_categories_and_brands(
            "推荐防晒", mock_llm, mock_session_factory, "",
        )

    system_prompt = captured_messages[0]["content"]
    assert "(无历史对话)" in system_prompt


@pytest.mark.asyncio
async def test_step1_none_memory_handles_gracefully():
    """conversation_id="" 时 prompt 包含 '(无历史记录)'，不崩溃。"""
    mock_llm = AsyncMock()

    captured_messages = []
    async def capture_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return json.dumps([{"category": "美妆护肤", "sub_category": "防晒", "brand": None}])

    mock_llm.chat = capture_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        await _extract_categories_and_brands(
            "推荐防晒", mock_llm, mock_session_factory, "",
        )

    system_prompt = captured_messages[0]["content"]
    assert "(无历史对话)" in system_prompt


# ---------------------------------------------------------------------------
# MULTI_CHAT_OPT: 自然语言价格调整测试
# ---------------------------------------------------------------------------

def test_step3_prompt_contains_price_adjustment_rules():
    """INTENT_EXTRACT_STEP3_SYSTEM 应包含自然语言价格调整规则。"""
    from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP3_SYSTEM
    assert "自然语言价格调整" in INTENT_EXTRACT_STEP3_SYSTEM
    assert "更平价" in INTENT_EXTRACT_STEP3_SYSTEM
    assert "基线" in INTENT_EXTRACT_STEP3_SYSTEM


@pytest.mark.asyncio
async def test_natural_language_price_down():
    """'300元以下' → '更平价' 后 max_price 应从 300 下降。"""
    mock_llm = AsyncMock()
    step1_json = json.dumps([{"category": "美妆护肤", "sub_category": "防晒", "brand": None}])
    step3_json = json.dumps([{
        "category": "美妆护肤", "sub_category": "防晒",
        "text": "", "min_price": 0, "max_price": 250,
        "order_num": 1, "brand": None,
    }])
    responses = [step1_json, step3_json]

    async def mock_chat(*args, **kwargs):
        return responses.pop(0)

    mock_llm.chat = mock_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    state = {
        "user_query": "请推荐更平价的产品",
        "conversation_id": "",
    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await intent_extract_node(state, llm=mock_llm,
                                        db_session_factory=mock_session_factory)

    reqs = result["requirements"]
    assert len(reqs) >= 1
    max_p = reqs[0]["max_price"]
    assert max_p < 300, f"期望 max_price 下调，实际 {max_p}"
    assert max_p >= 1, f"max_price 不应跌破底线"


@pytest.mark.asyncio
async def test_natural_language_price_up():
    """'200元左右' → '可以稍微贵一点' 后 max_price 应上升。"""
    mock_llm = AsyncMock()
    step1_json = json.dumps([{"category": "数码电子", "sub_category": "蓝牙耳机", "brand": None}])
    step3_json = json.dumps([{
        "category": "数码电子", "sub_category": "蓝牙耳机",
        "text": "", "min_price": 200, "max_price": 260,
        "order_num": 1, "brand": None,
    }])
    responses = [step1_json, step3_json]

    async def mock_chat(*args, **kwargs):
        return responses.pop(0)

    mock_llm.chat = mock_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    state = {
        "user_query": "可以稍微贵一点",
        "conversation_id": "",
    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await intent_extract_node(state, llm=mock_llm,
                                        db_session_factory=mock_session_factory)

    reqs = result["requirements"]
    max_p = reqs[0]["max_price"]
    assert max_p > 200, f"期望 max_price 上调，实际 {max_p}"


@pytest.mark.asyncio
async def test_no_baseline_no_relative_adjustment():
    """历史无显式数值时，'更便宜' 直接按语义提取价格，不崩溃。"""
    mock_llm = AsyncMock()
    step1_json = json.dumps([{"category": "美妆护肤", "sub_category": "防晒", "brand": None}])
    step3_json = json.dumps([{
        "category": "美妆护肤", "sub_category": "防晒",
        "text": "", "min_price": 0, "max_price": 500,
        "order_num": 1, "brand": None,
    }])
    responses = [step1_json, step3_json]

    async def mock_chat(*args, **kwargs):
        return responses.pop(0)

    mock_llm.chat = mock_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    state = {
        "user_query": "推荐更便宜的防晒霜",
        "conversation_id": "",
    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await intent_extract_node(state, llm=mock_llm,
                                        db_session_factory=mock_session_factory)

    reqs = result["requirements"]
    assert len(reqs) >= 1
    assert reqs[0]["max_price"] < 4294967295


@pytest.mark.asyncio
async def test_explicit_number_wins_over_natural_language():
    """当前查询含显式数值时，不走相对调整逻辑，直接使用显式数值。"""
    mock_llm = AsyncMock()
    step1_json = json.dumps([{"category": "美妆护肤", "sub_category": "防晒", "brand": None}])
    step3_json = json.dumps([{
        "category": "美妆护肤", "sub_category": "防晒",
        "text": "", "min_price": 0, "max_price": 150,
        "order_num": 1, "brand": None,
    }])
    responses = [step1_json, step3_json]

    async def mock_chat(*args, **kwargs):
        return responses.pop(0)

    mock_llm.chat = mock_chat

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.execute.return_value.fetchall.return_value = []

    state = {
        "user_query": "150元以下的有没有",
        "conversation_id": "",
    }

    with patch("app.services.category_lookup_service.fetch_category_context",
               AsyncMock(return_value=("", set()))):
        result = await intent_extract_node(state, llm=mock_llm,
                                        db_session_factory=mock_session_factory)

    reqs = result["requirements"]
    assert reqs[0]["max_price"] == 150
