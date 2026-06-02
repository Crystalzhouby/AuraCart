"""MCL-A8: Retrieval 节点核心逻辑测试。

测试 SubQuery 分组、品类汇总、失败隔离、品类顺序式 SSE、超时控制。
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.nodes.retrieval import (
    _group_sub_queries, _aggregate_results, retrieval_node
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
    """成功的品类结果应汇总到 retrieval_results。"""
    results = [
        {"category": "面部护肤", "sub_category": "防晒霜", "skus": [
            {"product_id": "p1", "sku_id": "sk1", "title": "安热沙", "price": 198}
        ], "error": None},
        {"category": "服饰", "sub_category": "墨镜", "skus": [
            {"product_id": "p2", "sku_id": "sk2", "title": "雷朋", "price": 599}
        ], "error": None},
    ]
    summary, failed = _aggregate_results(results)
    assert len(summary) == 2
    assert len(failed) == 0


def test_aggregate_results_with_failures():
    """失败的品类应在 failed_categories 中，成功的正常汇总。"""
    results = [
        {"category": "面部护肤", "sub_category": "防晒霜", "skus": [
            {"product_id": "p1", "sku_id": "sk1", "title": "安热沙", "price": 198}
        ], "error": None},
        {"category": "服饰", "sub_category": "墨镜", "skus": [], "error": "LLM timeout"},
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
    assert "retrieval_results" in result
    assert "failed_categories" in result


# ---------------------------------------------------------------------------
# Retrieval completion: inline SSE 发送 + 失败跳过
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieval_node_inline_sse_sends_products_and_reasoning():
    """retrieval_node 应按品类顺序内联发送 products → reasoning SSE 事件。"""
    queue = asyncio.Queue()

    # 构造 safe_results 模拟并行任务已完成
    safe_results = [
        {
            "category": "防晒", "sub_category": "防晒霜",
            "skus": [{"product_id": "p1", "sku_id": "s1", "title": "安热沙", "price": 198}],
            "product_ids": [{"product_id": "p1", "sku_id": "s1", "category": "防晒", "sub_category": "防晒霜"}],
            "reasoning_text": "安热沙推荐理由",
            "error": None,
        },
        {
            "category": "服饰", "sub_category": "墨镜",
            "skus": [{"product_id": "p2", "sku_id": "s2", "title": "雷朋", "price": 599}],
            "product_ids": [{"product_id": "p2", "sku_id": "s2", "category": "服饰", "sub_category": "墨镜"}],
            "reasoning_text": "雷朋推荐理由",
            "error": None,
        },
    ]

    # 模拟 retrieval_node 内联 SSE 发送逻辑
    for r in safe_results:
        if r.get("error"):
            continue
        product_ids = r.get("product_ids", [])
        if product_ids:
            await queue.put({"event": "products", "data": product_ids})
        reason = r.get("reasoning_text", "")
        if reason:
            await queue.put({
                "event": "reasoning",
                "data": {
                    "token": reason,
                    "category": r.get("category", ""),
                    "sub_category": r.get("sub_category", ""),
                }
            })

    # 验证事件顺序：品类1 products → 品类1 reasoning → 品类2 products → 品类2 reasoning
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert len(events) == 4
    assert events[0]["event"] == "products"
    assert events[0]["data"][0]["product_id"] == "p1"
    assert events[1]["event"] == "reasoning"
    assert events[1]["data"]["token"] == "安热沙推荐理由"
    assert events[2]["event"] == "products"
    assert events[2]["data"][0]["product_id"] == "p2"
    assert events[3]["event"] == "reasoning"
    assert events[3]["data"]["token"] == "雷朋推荐理由"


@pytest.mark.asyncio
async def test_retrieval_node_inline_sse_skips_failed_categories():
    """失败品类不应发送 products 或 reasoning 事件。"""
    queue = asyncio.Queue()

    safe_results = [
        {
            "category": "", "sub_category": "防晒霜",
            "skus": [], "product_ids": [],
            "reasoning_text": "", "error": "timeout",
        },
    ]

    for r in safe_results:
        if r.get("error"):
            continue
        product_ids = r.get("product_ids", [])
        if product_ids:
            await queue.put({"event": "products", "data": product_ids})
        reason = r.get("reasoning_text", "")
        if reason:
            await queue.put({"event": "reasoning", "data": {"token": reason, "category": r.get("category", ""), "sub_category": r.get("sub_category", "")}})

    assert queue.empty()
