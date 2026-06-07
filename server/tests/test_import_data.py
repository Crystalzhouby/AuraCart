# tests/test_import_data.py
"""测试数据导入流水线：商品分块逻辑。

chunk_product 函数将商品的 RAG 知识拆分为语义块（营销文案、
官方 FAQ、用户评价）以供 embedding 使用。这些测试验证典型输入
下的分块数量和内容。
"""

import pytest
from app.services.import_data_service import chunk_product


def test_chunk_product():
    """验证 chunk_product 将完整商品拆分为营销、FAQ 和评论三类分块。

    给定一个包含一条营销描述、一条 FAQ 条目和一条用户评价的商品，
    预期恰好生成三个分块，且每个分块的 source 标签、格式化文本内容
    和 metadata 字典均正确。

    预期分块：
      - marketing：原始描述文本，metadata 为空。
      - faq：格式化问答文本，metadata 包含原始问题。
      - user_review：格式化评价文本，metadata 包含昵称与评分。
    """
    product_data = {
        "product_id": "SKU001",
        "title": "安耐晒小金瓶防晒",
        "brand": "安耐晒",
        "category": "美妆护肤",
        "sub_category": "防晒",
        "base_price": 198.0,
        "image_path": "images/SKU001.jpg",
        "skus": [
            {
                "sku_id": "SKU001_60ml",
                "properties": {"容量": "60ml"},
                "price": 198.0,
            }
        ],
        "rag_knowledge": {
            "marketing_description": "持久防晒，防水防汗。",
            "official_faq": [
                {"question": "适合油皮吗？", "answer": "适合，清爽配方。"}
            ],
            "user_reviews": [
                {"nickname": "用户A", "rating": 5, "content": "很好用，不油腻"}
            ],
        },
    }

    chunks = chunk_product(product_data)

    # 预期 3 个分块：marketing + faq + user_review
    assert len(chunks) == 3
    assert chunks[0] == ("marketing", "持久防晒，防水防汗。", {})
    assert chunks[1] == (
        "faq",
        "问题：适合油皮吗？\n回答：适合，清爽配方。",
        {"question": "适合油皮吗？"},
    )
    assert chunks[2] == (
        "user_review",
        "用户用户A评分5分，评价：很好用，不油腻",
        {"nickname": "用户A", "rating": 5},
    )


def test_chunk_product_no_faqs():
    """验证当 FAQ 和评论为空时，chunk_product 仅生成营销分块。

    当 rag_knowledge 部分仅包含营销描述（无 FAQ，无评论），
    函数应恰好返回一个分块。
    """
    product_data = {
        "product_id": "SKU002",
        "title": "测试商品",
        "brand": "测试",
        "category": "测试",
        "base_price": 10.0,
        "skus": [{"sku_id": "SKU002_1", "properties": {}, "price": 10.0}],
        "rag_knowledge": {
            "marketing_description": "测试描述",
            "official_faq": [],
            "user_reviews": [],
        },
    }

    chunks = chunk_product(product_data)

    # FAQ 和评论列表为空时，仅保留营销分块
    assert len(chunks) == 1
