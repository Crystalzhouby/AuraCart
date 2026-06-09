"""Retrieval 节点测试 — 重构后。

测试 intent-to-SubQuery 转换、category_task 流程、product_retrieve_node SSE 发送。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.nodes.product_retrieve_agent import (
    _intent_to_sub_queries,
    product_retrieve_node,
)
from app.services.retriever_service import SubQuery


# ---------------------------------------------------------------------------
# _intent_to_sub_queries 测试
# ---------------------------------------------------------------------------

def test_intent_to_sub_queries_basic():
    """基本意图应生成 keyword + semantic + structured_filter SubQuery。"""
    intent = {
        "category": "美妆护肤",
        "sub_category": "防晒",
        "text": "高倍数防晒 不粘腻",
        "min_price": 0,
        "max_price": 200,
        "order_num": 1,
        "brand": ["安热沙"],
    }
    subs = _intent_to_sub_queries(intent)
    assert isinstance(subs, list)
    assert len(subs) >= 3  # keyword + semantic + category + sub_category + price + brand

    strategies = [s.strategy for s in subs]
    assert "keyword" in strategies
    assert "semantic" in strategies
    assert "structured_filter" in strategies

    # 验证 keyword
    kw = [s for s in subs if s.strategy == "keyword"]
    assert len(kw) == 1
    assert kw[0].text == "高倍数防晒 不粘腻"

    # 验证 semantic
    sem = [s for s in subs if s.strategy == "semantic"]
    assert len(sem) == 1
    assert sem[0].text == "高倍数防晒 不粘腻"


def test_intent_to_sub_queries_minimal():
    """最小意图（仅 text）应生成 keyword + semantic SubQuery。"""
    intent = {
        "category": None,
        "sub_category": None,
        "text": "跑鞋推荐",
        "min_price": 0,
        "max_price": 4294967295,
        "order_num": 1,
        "brand": None,
    }
    subs = _intent_to_sub_queries(intent)
    # keyword + semantic，无 structured_filter
    assert len(subs) == 2
    strategies = [s.strategy for s in subs]
    assert "keyword" in strategies
    assert "semantic" in strategies


def test_intent_to_sub_queries_with_price_bounds():
    """有价格边界时应生成 price structured_filter。"""
    intent = {
        "category": "服饰运动",
        "sub_category": "跑步鞋",
        "text": "轻量化",
        "min_price": 100,
        "max_price": 500,
        "order_num": 1,
        "brand": None,
    }
    subs = _intent_to_sub_queries(intent)
    price_subs = [s for s in subs if s.field == "price"]
    assert len(price_subs) == 2  # min (gt) + max (lt)


def test_intent_to_sub_queries_empty_text():
    """text 为空时不应生成 semantic SubQuery。"""
    intent = {
        "category": "美妆护肤",
        "sub_category": "面霜",
        "text": "",
        "min_price": 0,
        "max_price": 4294967295,
        "order_num": 1,
        "brand": None,
    }
    subs = _intent_to_sub_queries(intent)
    strategies = [s.strategy for s in subs]
    assert "semantic" not in strategies


# ---------------------------------------------------------------------------
# product_retrieve_node 测试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_product_retrieve_node_empty_requirements():
    """空 requirements 时 early return 空结果。"""
    state = {
        "user_query": "推荐",
        "requirements": [],
        "conversation_id": "",
    }

    result = await product_retrieve_node(
        state,
        emb_service=MagicMock(),
        async_session_factory=MagicMock(),
    )
    assert result["retrieval_results"] == []
    assert result["failed_categories"] == []


from unittest.mock import patch

