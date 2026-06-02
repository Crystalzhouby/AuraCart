"""MCL-A5: Extraction 节点测试。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.nodes.extraction import extraction_node, _format_history_context


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
async def test_extraction_no_longer_appends_conversation_history():
    """Extraction 不应再追加 conversation_history（已移至 retrieval_node）。

    验证 extraction 的返回结果中不包含 conversation_history 字段，
    避免当前 requirements 在 state 中被重复注入。
    """
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

    # Extraction 不再返回 conversation_history，避免与 requirements 重复
    assert "conversation_history" not in result
    assert "requirements" in result


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


@pytest.mark.asyncio
async def test_extraction_no_longer_truncates_history():
    """Extraction 不应再调用 truncate_by_tokens（已移至 retrieval_node）。

    验证 extraction 不再执行 conversation_history 的截断逻辑。
    """
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

    with patch("app.agent.memory.truncate_by_tokens") as mock_truncate:
        result = await extraction_node(state, llm=mock_llm)

    # Extraction 不再调用截断
    mock_truncate.assert_not_called()
    assert "requirements" in result


# ---------------------------------------------------------------------------
# Extraction completion: conversation history formatting
# ---------------------------------------------------------------------------


def test_format_history_context_empty():
    """空历史应返回空字符串。"""
    assert _format_history_context([]) == ""


def test_format_history_context_extracts_sub_queries():
    """应从 conversation_history 中提取子查询并格式化为历史需求文本。"""
    history = [
        {"sub_queries": [
            {"text": "蓝牙耳机", "strategy": "keyword", "category": "数码电子", "sub_category": "蓝牙耳机"},
        ]},
        {"sub_queries": [
            {"text": "价格低于200", "strategy": "structured_filter", "field": "price", "operator": "lt", "value": 200},
        ]},
    ]
    result = _format_history_context(history)
    assert "蓝牙耳机" in result
    assert "数码电子" in result
    assert "价格低于200" in result
    assert "历史需求" in result


def test_format_history_context_handles_missing_fields():
    """SubQuery 缺少可选字段时不应崩溃。"""
    history = [
        {"sub_queries": [
            {"text": "跑鞋", "strategy": "keyword"},
        ]},
    ]
    result = _format_history_context(history)
    assert "跑鞋" in result


@pytest.mark.asyncio
async def test_extraction_injects_history_context():
    """Extraction 应将历史需求以结构化格式注入提示词。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(json.dumps([
        {"text": "墨镜", "strategy": "keyword",
         "field": None, "operator": None, "value": None, "expanded_values": None,
         "category": "服饰", "sub_category": "墨镜"},
    ]))

    state = {
        "user_query": "再推荐一个墨镜",
        "conversation_history": [
            {"sub_queries": [{"text": "去三亚度假", "strategy": "semantic", "category": None, "sub_category": None}]},
        ],
    }

    result = await extraction_node(state, llm=mock_llm)

    assert "requirements" in result
    assert len(result["requirements"]["sub_queries"]) == 1
    # conversation_history 不再由 extraction 追加
    assert "conversation_history" not in result
