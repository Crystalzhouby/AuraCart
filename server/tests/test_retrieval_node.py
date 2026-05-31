"""MCL-A8: Retrieval 节点核心逻辑测试。

测试 SubQuery 分组、品类汇总、失败隔离、品类顺序式 SSE、超时控制。
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.nodes.retrieval import (
    _group_sub_queries, _aggregate_results, retrieval_node, _send_reasoning_sequential
)


def test_group_sub_queries_by_sub_category():
    """SubQuery 应按 sub_category 分组。"""
    subs = [
        {"text": "防晒霜", "strategy": "keyword", "category": "面部护肤", "sub_category": "防晒霜"},
        {"text": "高倍防晒", "strategy": "semantic", "category": "面部护肤", "sub_category": "防晒霜"},
        {"text": "墨镜", "strategy": "keyword", "category": "服饰", "sub_category": "墨镜"},
    ]
    groups = _group_sub_queries(subs)
    assert "防晒霜" in groups
    assert "墨镜" in groups
    assert len(groups["防晒霜"]) == 2
    assert len(groups["墨镜"]) == 1


def test_group_sub_queries_fallback_to_category():
    """无 sub_category 时回退到 category 分组。"""
    subs = [
        {"text": "test", "strategy": "keyword", "category": "面部护肤", "sub_category": None},
    ]
    groups = _group_sub_queries(subs)
    assert "面部护肤" in groups


def test_group_sub_queries_fallback_to_default():
    """无 category 也无 sub_category 时归入 default。"""
    subs = [
        {"text": "test", "strategy": "semantic", "category": None, "sub_category": None},
    ]
    groups = _group_sub_queries(subs)
    assert "default" in groups


def test_aggregate_results_success():
    """成功的品类结果应汇总到 products_summary。"""
    results = [
        {"category": "面部护肤", "sub_category": "防晒霜", "products_summary": [
            {"product_id": "p1", "sku_id": "sk1", "title": "安热沙", "price": 198}
        ], "error": None},
        {"category": "服饰", "sub_category": "墨镜", "products_summary": [
            {"product_id": "p2", "sku_id": "sk2", "title": "雷朋", "price": 599}
        ], "error": None},
    ]
    summary, failed = _aggregate_results(results)
    assert len(summary) == 2
    assert len(failed) == 0


def test_aggregate_results_with_failures():
    """失败的品类应在 failed_categories 中，成功的正常汇总。"""
    results = [
        {"category": "面部护肤", "sub_category": "防晒霜", "products_summary": [
            {"product_id": "p1", "sku_id": "sk1", "title": "安热沙", "price": 198}
        ], "error": None},
        {"category": "服饰", "sub_category": "墨镜", "products_summary": [], "error": "LLM timeout"},
    ]
    summary, failed = _aggregate_results(results)
    assert len(summary) == 1  # 只有成功的
    assert len(failed) == 1   # 一个失败
    assert failed[0]["sub_category"] == "墨镜"


def test_aggregate_results_empty_input():
    """空输入返回空。"""
    summary, failed = _aggregate_results([])
    assert summary == []
    assert failed == []


@pytest.mark.asyncio
async def test_retrieval_node_basic():
    """Retrieval 节点的基本流程：读取 SubQuery → 分组 → 聚合。"""
    state = {
        "user_query": "防晒霜和墨镜",
        "requirements": {
            "sub_queries": [
                {"text": "防晒霜", "strategy": "keyword", "category": "面部护肤", "sub_category": "防晒霜",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
                {"text": "墨镜", "strategy": "keyword", "category": "服饰", "sub_category": "墨镜",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
            ]
        },
        "conversation_history": [],
    }
    # Mock async_session
    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session)))

    # Mock LLM
    mock_llm = MagicMock()

    result = await retrieval_node(
        state,
        llm=mock_llm,
        emb_service=MagicMock(),
        async_session_factory=mock_session_factory,
        _sse_queue=None,
    )
    assert "products_summary" in result
    assert "failed_categories" in result


# ---------------------------------------------------------------------------
# Retrieval completion: category-sequential SSE + timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_reasoning_sequential_ordered_by_groups():
    """品类顺序式：reasoning 应按 groups 键的顺序串行发送。"""
    queue = asyncio.Queue()

    # 模拟 2 个品类的结果，各自有缓存的 reasoning tokens
    safe_results = [
        {
            "category": "面部护肤", "sub_category": "防晒霜",
            "products_summary": [], "error": None,
            "reasoning_tokens": ["安", "热", "沙"],
        },
        {
            "category": "服饰", "sub_category": "墨镜",
            "products_summary": [], "error": None,
            "reasoning_tokens": ["雷", "朋"],
        },
    ]
    group_keys = ["防晒霜", "墨镜"]

    await _send_reasoning_sequential(safe_results, group_keys, queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # 应有 2 个 reasoning 事件（每品类一个完整块）
    reasoning_events = [e for e in events if e["event"] == "reasoning"]
    assert len(reasoning_events) == 2
    # 第一品类
    assert reasoning_events[0]["data"]["token"] == "安热沙"
    assert reasoning_events[0]["data"]["category"] == "面部护肤"
    # 第二品类
    assert reasoning_events[1]["data"]["token"] == "雷朋"
    assert reasoning_events[1]["data"]["category"] == "服饰"


@pytest.mark.asyncio
async def test_send_reasoning_sequential_skips_failed():
    """失败的品类不应发送 reasoning 事件。"""
    queue = asyncio.Queue()

    safe_results = [
        {
            "category": "", "sub_category": "防晒霜",
            "products_summary": [], "error": "timeout",
            "reasoning_tokens": [],
        },
    ]
    group_keys = ["防晒霜"]

    await _send_reasoning_sequential(safe_results, group_keys, queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # 失败的品类不发送 events (done 由 retrieval_node 发送)
    reasoning_events = [e for e in events if e["event"] == "reasoning"]
    assert len(reasoning_events) == 0


@pytest.mark.asyncio
async def test_send_reasoning_sequential_empty_queue():
    """无结果时不抛异常。"""
    queue = asyncio.Queue()
    await _send_reasoning_sequential([], [], queue)
    assert queue.empty()


@pytest.mark.asyncio
async def test_retrieval_node_sends_sequential_reasoning():
    """Retrieval 节点应发送品类顺序式 reasoning SSE 事件。"""
    queue = asyncio.Queue()

    state = {
        "user_query": "防晒霜和墨镜",
        "requirements": {
            "sub_queries": [
                {"text": "防晒霜", "strategy": "keyword", "category": "面部护肤", "sub_category": "防晒霜",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
                {"text": "墨镜", "strategy": "keyword", "category": "服饰", "sub_category": "墨镜",
                 "field": None, "operator": None, "value": None, "expanded_values": None},
            ]
        },
        "conversation_history": [],
        "_sse_queue": queue,
    }

    mock_session = AsyncMock()
    mock_session_factory = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session)))
    mock_llm = MagicMock()

    result = await retrieval_node(
        state,
        llm=mock_llm,
        emb_service=MagicMock(),
        async_session_factory=mock_session_factory,
    )

    assert "products_summary" in result
    assert "failed_categories" in result

    # 验证 SSE 事件已发送
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    event_types = [e["event"] for e in events]
    assert "done" in event_types
    # done 事件应包含 total_categories
    done_event = [e for e in events if e["event"] == "done"][0]
    assert "total_categories" in done_event["data"]
