# tests/test_generator.py
"""测试 Generator 服务：流式推荐生成与上下文构建。"""

import pytest
from unittest.mock import AsyncMock
from app.rag.generator import Generator


# ---------------------------------------------------------------------------
# _build_context — 新扁平 SKU 格式（选项 A：内部按 product_id 分组）
# ---------------------------------------------------------------------------

def test_build_context_single_sku():
    """单条 SKU → 渲染为一个 product 下的一条 SKU。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        }
    ]

    ctx = generator._build_context(skus)

    assert "安耐晒小金瓶" in ctx
    assert "安耐晒" in ctx
    assert "美妆护肤" in ctx
    assert "198.0" in ctx
    assert "s_p1_60ml" in ctx
    assert "60ml" in ctx


def test_build_context_multi_sku_same_product():
    """同一 product 下多个 SKU → 合并到一个 product 分组下。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        },
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_30ml",
            "properties": {"容量": "30ml"},
            "price": 128.0,
            "stock": 15,
        },
    ]

    ctx = generator._build_context(skus)

    # product 标题只出现一次
    assert ctx.count("安耐晒小金瓶") == 1
    # 两个 SKU 都在
    assert "s_p1_60ml" in ctx
    assert "s_p1_30ml" in ctx
    assert "60ml" in ctx
    assert "30ml" in ctx


def test_build_context_multi_sku_different_products():
    """不同 product 的 SKU → 各自独立分组。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        },
        {
            "product_id": "p2",
            "title": "碧柔水感防晒霜",
            "brand": "碧柔",
            "category": "美妆护肤",
            "base_price": 79.0,
            "sku_id": "s_p2_50g",
            "properties": {"容量": "50g"},
            "price": 79.0,
            "stock": 88,
        },
    ]

    ctx = generator._build_context(skus)

    # 两个 product 标题各出现一次
    assert "1. 安耐晒小金瓶" in ctx
    assert "2. 碧柔水感防晒霜" in ctx
    assert "安耐晒" in ctx
    assert "碧柔" in ctx


def test_build_context_sku_without_optional_fields():
    """SKU 缺少 brand/category/properties → 不崩溃，优雅跳过。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "某商品",
            "brand": None,
            "category": None,
            "base_price": None,
            "sku_id": "s_p1_x",
            "properties": None,
            "price": 50.0,
            "stock": 0,
        }
    ]

    ctx = generator._build_context(skus)

    assert "某商品" in ctx
    assert "s_p1_x" in ctx
    assert "50.0" in ctx
    # brand/category 不出现
    assert "品牌" not in ctx
    assert "品类" not in ctx


def test_build_context_empty_skus():
    """空 SKU 列表 → 返回空字符串。"""
    generator = Generator(llm=AsyncMock())
    ctx = generator._build_context([])
    assert ctx == ""


# ---------------------------------------------------------------------------
# generate() 流式输出 — 适配新格式后保持不变
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_stream():
    """验证 generate() 从 LLM chat_stream 中按 token 异步产出。"""
    mock_llm = AsyncMock()

    async def fake_stream(messages, temperature=None):
        yield "为您"
        yield "推荐"
        yield "以下商品"

    mock_llm.chat_stream = fake_stream

    generator = Generator(llm=mock_llm)

    skus = [
        {
            "product_id": "P1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "P1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        }
    ]

    user_query = "推荐一款防晒霜"
    tokens = []
    async for token in generator.generate(skus, user_query):
        tokens.append(token)

    assert tokens == ["为您", "推荐", "以下商品"]
